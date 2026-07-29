using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using ObjectStorageClient.App.Services;
using ObjectStorageClient.Core.Local;

namespace ObjectStorageClient.App.ViewModels;

/// <summary>
/// Left half of the window: the local file system, mirroring FileZilla's local pane.
/// </summary>
public sealed partial class LocalBrowserViewModel : ViewModelBase
{
    private readonly LogViewModel _log;
    private readonly IDialogService _dialogs;

    public LocalBrowserViewModel(LogViewModel log, IDialogService dialogs, ITransferCoordinator coordinator)
    {
        _log = log;
        _dialogs = dialogs;
        Coordinator = coordinator;

        foreach (LocalEntry root in LocalFileSystem.GetRoots())
        {
            Roots.Add(root);
        }

        Navigate(LocalFileSystem.GetHomeDirectory());
    }

    public ITransferCoordinator Coordinator { get; }

    /// <summary>Drive letters (Windows) or home/root/mount points (Unix).</summary>
    public ObservableCollection<LocalEntry> Roots { get; } = [];

    public ObservableCollection<LocalEntry> Entries { get; } = [];

    /// <summary>Kept in sync by the view's selection handler; drives the upload command.</summary>
    public ObservableCollection<LocalEntry> SelectedEntries { get; } = [];

    [ObservableProperty]
    private string _currentPath = string.Empty;

    [ObservableProperty]
    private bool _showHiddenFiles;

    [ObservableProperty]
    private string _statusText = string.Empty;

    partial void OnShowHiddenFilesChanged(bool value)
    {
        _ = value;
        Refresh();
    }

    /// <summary>Lists <paramref name="path"/>, leaving the current view untouched if it cannot be read.</summary>
    public void Navigate(string path)
    {
        try
        {
            string fullPath = Path.GetFullPath(path);
            if (!Directory.Exists(fullPath))
            {
                _log.Error($"Local directory not found: {fullPath}");
                return;
            }

            IReadOnlyList<LocalEntry> entries = LocalFileSystem.List(fullPath, showHidden: ShowHiddenFiles);

            CurrentPath = fullPath;
            SelectedEntries.Clear();
            Entries.Clear();

            foreach (LocalEntry entry in entries)
            {
                Entries.Add(entry);
            }

            int files = entries.Count(entry => !entry.IsDirectory);
            int directories = entries.Count(entry => entry.IsDirectory && !entry.IsParentLink);
            StatusText = $"{directories} directories, {files} files";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            _log.Error($"Cannot open '{path}'", ex);
        }
    }

    [RelayCommand]
    private void Refresh() => Navigate(CurrentPath);

    [RelayCommand]
    private void NavigateUp()
    {
        DirectoryInfo? parent = Directory.GetParent(CurrentPath);
        if (parent is not null)
        {
            Navigate(parent.FullName);
        }
    }

    /// <summary>
    /// Double-click / Enter: descend into a directory, or queue a file for upload — the same
    /// split FileZilla uses, so activating a file is the quickest way to transfer it.
    /// </summary>
    [RelayCommand]
    private void Open(LocalEntry? entry)
    {
        if (entry is null)
        {
            return;
        }

        if (entry.IsDirectory)
        {
            Navigate(entry.FullPath);
            return;
        }

        Coordinator.QueueUpload([entry]);
    }

    [RelayCommand]
    private async Task CreateDirectoryAsync()
    {
        string? name = await _dialogs.PromptAsync("Create directory", "New directory name:").ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }

        try
        {
            Directory.CreateDirectory(Path.Combine(CurrentPath, name.Trim()));
            _log.Info($"Created local directory '{name}'.");
            Refresh();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            await _dialogs.ShowErrorAsync("Create directory", ex.Message).ConfigureAwait(true);
        }
    }

    [RelayCommand]
    private async Task DeleteSelectedAsync()
    {
        List<LocalEntry> targets = [.. SelectedEntries.Where(entry => !entry.IsParentLink)];
        if (targets.Count == 0)
        {
            return;
        }

        bool confirmed = await _dialogs
            .ConfirmAsync("Delete", $"Delete {targets.Count} local item(s)? This cannot be undone.")
            .ConfigureAwait(true);

        if (!confirmed)
        {
            return;
        }

        foreach (LocalEntry entry in targets)
        {
            try
            {
                if (entry.IsDirectory)
                {
                    Directory.Delete(entry.FullPath, recursive: true);
                }
                else
                {
                    File.Delete(entry.FullPath);
                }

                _log.Info($"Deleted {entry.FullPath}");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                _log.Error($"Failed to delete '{entry.FullPath}'", ex);
            }
        }

        Refresh();
    }

    /// <summary>Queues the current selection for upload into the remote pane's location.</summary>
    [RelayCommand]
    private void Upload()
    {
        List<LocalEntry> targets = [.. SelectedEntries.Where(entry => !entry.IsParentLink)];
        if (targets.Count == 0)
        {
            return;
        }

        Coordinator.QueueUpload(targets);
    }
}
